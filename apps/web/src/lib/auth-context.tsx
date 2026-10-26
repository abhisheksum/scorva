'use client';

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { UserProfile } from '@/types/api';
import { api, ApiClientError } from '@/lib/api-client';

interface AuthContextType {
  user: UserProfile | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  refreshUser: (initialUser?: UserProfile) => Promise<UserProfile | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const router = useRouter();

  const refreshUser = useCallback(async (initialUser?: UserProfile): Promise<UserProfile | null> => {
    if (initialUser) {
      setUser(initialUser);
      setIsLoading(false);
      return initialUser;
    }

    try {
      const data = await api.getMe();
      const userProfile =
        data && typeof data === 'object' && 'user' in (data as unknown as Record<string, unknown>)
          ? (data as unknown as { user: UserProfile }).user
          : (data as UserProfile);
      setUser(userProfile);
      return userProfile;
    } catch (err: unknown) {
      setUser(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (err: unknown) {
      console.warn('Logout request failed or network error:', err);
    } finally {
      setUser(null);
      router.push('/login');
    }
  }, [router]);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        refreshUser,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
